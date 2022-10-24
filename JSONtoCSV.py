import json

#file_list = ['../data/2021/C1U1.csv','../data/2021/C1U2.csv','../data/2021/C1U3.csv','../data/2021/C1U4.csv','../data/2021/C1U5.csv']
#file_list = ['../data/2021/C2U1.csv','../data/2021/C2U2U3.csv','../data/2021/C2U4U5.csv']
file_list = ['../data/2022TreeData/C3U1.csv','../data/2022TreeData/C3U2.csv','../data/2022TreeData/C3U3.csv','../data/2022TreeData/C3U4U5.csv']

outfilename = '../data/2022TreeData/C3.csv'

outfile = open(outfilename,'w')
for filename in file_list:
	with open(filename,'r') as infile:
		data = json.load(infile)
		for point in data:
			outfile.write(str(point[0]) + "," + str(point[1]) + "," + str(point[2]) + "\n")
			
outfile.close()
			
